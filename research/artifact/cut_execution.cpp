#define SCOPECUT_LIBRARY
#include "cut.cpp"

namespace wide {
using namespace admission;
constexpr int repetitions=3;
constexpr int max_slices=384;

struct Lookup {

    U outputs=0,one=0,zero=0;
    Node cache;
    int col=-1;
    enum Kind {bitmap,single,always,never} kind=bitmap;
    I count(const Columns&cols,Range z)const{
        if(kind==bitmap)return cache.count(z);
        if(kind==never)return 0;
        if(kind==always)return z.r-z.l;
        I k=cols.rankcol(col,z.r)-cols.rankcol(col,z.l);
        return one?k:z.r-z.l-k;
    }
};
struct Program {
    vector<SharedNode> projected;
    const vector<SharedNode>* terms=nullptr;
    vector<Lookup> cache;
    Cost extra=0;
    void prepare(const FixedPlan&p,const vector<Q>&q,Columns&cols,U keep){
        if(keep==first_bits(p.b))terms=&p.terms;
        else if(keep){
            for(auto e:p.terms){
                e.plus&=keep;e.minus&=keep;
                if(e.plus|e.minus)projected.push_back(e);
            }
            terms=&projected;
        }
        map<pair<U,U>,U> groups;for(int j=0;j<p.b;j++)if(!((keep>>j)&1))groups[{q[j].one,q[j].zero}]|=U(1)<<j;
        for(auto [pred,mask]:groups){
            Lookup l;l.outputs=mask;l.one=pred.first;l.zero=pred.second;U active=l.one|l.zero;
            if(l.one&l.zero)l.kind=Lookup::never;
            else if(!active)l.kind=Lookup::always;
            else if(has_single_bit(active)){l.col=countr_zero(active);l.kind=Lookup::single;}
            else{
                Q rule{"",l.one,l.zero,{}};l.cache=cols.cache(rule);
                extra+=8*l.cache.w.size()+4*l.cache.pref.size();
            }
            cache.push_back(move(l));
        }
    }
    void apply(const Tree&t,const Columns&cols,Range z,int64_t*out,int b)const{
        if(terms){
            fill_n(out,b,0);
            for(auto e:*terms){
                auto k=e.node?t.t[e.node].count(z):z.r-z.l;
                each(e.plus,[&](int j){out[j]+=k;});
                each(e.minus,[&](int j){out[j]-=k;});
            }
        }
        for(auto &l:cache){int64_t count=l.count(cols,z);each(l.outputs,[&](int j){out[j]=count;});}
    }
};
vector<Range> make_ranges(I n,int group,int width){
    mt19937_64 g(90163ULL+1009*group+width);
    constexpr double widths[]={0.0001,0.001,0.01,0.1,0.5,1};
    vector<Range> out;for(int k=0;k<max_slices;k++){
        I size=I(max<Cost>(1,min<Cost>(n,llround(n*widths[(k+group)%6]))));
        uniform_int_distribution<I> start(0,n-size);I l=start(g);out.push_back({l,I(l+size)});
    }return out;
}
vector<int64_t> raw_counts(const vector<U>&rows,const vector<Q>&q,const vector<Range>&ranges){
    vector<I> stops;for(auto z:ranges){stops.push_back(z.l);stops.push_back(z.r);}
    sort(stops.begin(),stops.end());stops.erase(unique(stops.begin(),stops.end()),stops.end());
    vector<int64_t> result(ranges.size()*q.size());
    for(int j=0;j<int(q.size());j++){
        vector<I> pref(stops.size());I at=0,total=0;U one=q[j].one,zero=q[j].zero,mask=one|zero;
        for(size_t i=0;i<stops.size();i++){
            if(!(one&zero))for(I r=at;r<stops[i];r++)total+=((rows[r]&mask)==one);
            at=stops[i];pref[i]=total;
        }
        for(size_t k=0;k<ranges.size();k++){
            size_t l=lower_bound(stops.begin(),stops.end(),ranges[k].l)-stops.begin();
            size_t r=lower_bound(stops.begin(),stops.end(),ranges[k].r)-stops.begin();
            result[k*q.size()+j]=pref[r]-pref[l];
        }
    }return result;
}
static U digest(const vector<int64_t>&a){U h=14695981039346656037ull;for(auto n:a)h=(h^U(n))*1099511628211ull;return h;}
static void run_dataset(const string&pre,ostream&out){
    auto rows=read_rows(pre);auto q=readq(pre+".queries");auto t0=Clock::now();Tree t(rows);Cost tree_ns=elapsed(t0);
    t0=Clock::now();Columns cols(rows);Cost cols_ns=elapsed(t0);
    U tree_bytes=t.t.capacity()*sizeof(Node),col_bytes=0;
    for(auto& v:t.t)tree_bytes+=v.p.capacity()*sizeof(I)+v.pref.capacity()*sizeof(I)+v.w.capacity()*sizeof(U);
    for(int j=0;j<64;j++)col_bytes+=cols.w[j].capacity()*sizeof(U)+cols.pref[j].capacity()*sizeof(I);
    mt19937 rng(19802);
    for(int b:{16,32,64})for(size_t first=0;first+b<=q.size();first+=b){
        vector<Q> bundle(q.begin()+first,q.begin()+first+b);auto ranges=make_ranges(t.n,int(first/b),b);
        auto expected=raw_counts(rows,bundle,ranges);
        for(int rep=0;rep<repetitions;rep++){
            auto start=Clock::now();auto p=compile_terms(t,bundle);Cost union_ns=elapsed(start);
            start=Clock::now();price_terms(t,bundle,p);Cost price_ns=elapsed(start);
            for(int H:{1,24,max_slices}){
                array<int,3> order{0,1,2};shuffle(order.begin(),order.end(),rng);
                vector<int64_t> actual(size_t(H)*b);
                for(int policy:order){
                    U keep;Cost cut_ns=0;
                    if(policy==0){start=Clock::now();keep=p.solve(H).first;cut_ns=elapsed(start);}
                    else keep=policy==1?0:first_bits(b);
                    start=Clock::now();Program pr;pr.prepare(p,bundle,cols,keep);Cost setup_ns=elapsed(start);

                    fill(actual.begin(),actual.end(),-1);
                    start=Clock::now();
                    for(int k=0;k<H;k++)pr.apply(t,cols,ranges[k],&actual[size_t(k)*b],b);
                    Cost exec_ns=elapsed(start);
                    if(!equal(actual.begin(),actual.end(),expected.begin()))throw runtime_error("Wrong wide output "+pre);
                    out<<stem(pre)<<'\t'<<first<<'\t'<<b<<'\t'<<H<<'\t'<<rep<<'\t'<<(policy==0?"cut":policy==1?"cache":"tree")<<'\t'
                       <<keep<<'\t'<<popcount(keep)<<'\t'<<union_ns<<'\t'<<(policy==0?price_ns:0)<<'\t'<<cut_ns<<'\t'<<setup_ns<<'\t'<<exec_ns<<'\t'
                       <<pr.extra<<'\t'<<tree_bytes<<'\t'<<col_bytes<<'\t'<<tree_ns<<'\t'<<cols_ns<<'\t'<<digest(actual)<<'\n';
                }
            }
        }
    }out.flush();cout<<stem(pre)<<endl;
}
}
int main(int argc,char**argv){
    try{
        if(argc<3)throw runtime_error("cut_execution.exe output.tsv prefixes...");
        ofstream out(argv[1]);if(!out)throw runtime_error("Cannot open output");
        out<<"dataset\tfirst\twidth\thorizon\trep\tmethod\tkeep_mask\tkept\tunion_ns\tprice_ns\tcut_ns\tsetup_ns\texec_ns\tcache_bytes\ttree_bytes\tcolumn_bytes\ttree_build_ns\tcolumn_build_ns\tdigest\n";
        for(int i=2;i<argc;i++)wide::run_dataset(argv[i],out);
        return 0;
    }catch(const exception&e){cerr<<e.what()<<'\n';return 1;}
}
