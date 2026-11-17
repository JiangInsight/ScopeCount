
#define main scopecount_bundle_main
#include "bundles.cpp"
#undef main
#include <filesystem>
#include <numeric>
#include <random>

namespace gate {
using Cost = int64_t;
constexpr unsigned B=8, K=1u<<B, ALL=K-1;
constexpr size_t CAP=4096;
struct Witness { U l,r; Cost price; };
Cost read_price(const Node& n) {return n.w.empty()?2+2*Cost(bit_width(n.p.size())):5;}
bool accepts(U v,const Q& q) {return (v&q.one)==q.one && !(v&q.zero);}
struct Catalog {
    vector<Witness> pairs;
    Cost sum_prices=0;
    explicit Catalog(const Tree& t) {
        for(const auto& n:t.t) if(n.bit>=0 && t.t[n.a].bit<0 && t.t[n.b].bit<0){
            const auto& l=t.t[n.a]; const auto& r=t.t[n.b];
            pairs.push_back({l.shape,r.shape,min(read_price(l),read_price(r))});
            sum_prices+=pairs.back().price;
        }

        mt19937_64 random(20261109);
        for(size_t k=pairs.size(); k>1; --k) swap(pairs[k-1],pairs[random()%k]);
    }
};
struct Group {unsigned bits; Cost build;};
vector<Group> group(const vector<Q>& q,I n) {
    vector<Group> groups;
    for(unsigned i=0;i<B;i++){
        bool seen=false;
        for(auto& g:groups){
            const auto& first=q[countr_zero(g.bits)];
            if(first.one==q[i].one && first.zero==q[i].zero) {
                g.bits|=1u<<i; seen=true; break;
            }
        }
        if(!seen){
            auto count=popcount(q[i].one|q[i].zero);
            Cost prep=count>1 && !(q[i].one&q[i].zero) ? ((Cost(n)+63)/64)*(count+3):0;
            groups.push_back({1u<<i,prep});
        }
    }
    return groups;
}
unsigned disagreement(const Witness& p,const vector<Q>& q){
    unsigned d=0;
    for(unsigned j=0;j<B;j++) if(accepts(p.l,q[j])!=accepts(p.r,q[j])) d|=1u<<j;
    return d;
}

Cost saved(unsigned keep,const vector<Group>& groups,Cost h) {
    Cost result=5*h*popcount(keep);
    for(auto g:groups) if((keep&g.bits)==g.bits)result+=g.build;
    return result;
}
struct Tally {
    array<Cost,K> fixed{};
    array<Cost,B> updates{};
    Cost total=0;
    void add(unsigned d,Cost price){
        if(!d)return;
        fixed[d]+=price;total+=price;
        for(unsigned m=d;m;m&=m-1)++updates[countr_zero(m)];
    }
    bool proves(Cost h,const vector<Group>& groups) const {

        for(unsigned j=0;j<B;j++){
            Cost budget=saved(1u<<j,groups,h);

            if(h*(total+updates[j])<budget)return false;
        }
        auto subset=fixed;
        for(unsigned bit=1;bit<K;bit<<=1)
            for(unsigned mask=0;mask<K;mask++)if(mask&bit)subset[mask]+=subset[mask^bit];
        array<Cost,K> add{};
        for(unsigned s=1;s<K;s++){
            add[s]=add[s&(s-1)]+updates[countr_zero(s)];
            if(h*(total-subset[ALL^s]+add[s])<saved(s,groups,h))return false;
        }
        return true;
    }
};
struct Decision {bool yes=false;size_t sampled=0;};
Decision decide(const Catalog& cat,const vector<Q>& q,I n,Cost h){
    const auto groups=group(q,n);
    for(auto g:groups){

        Cost upper=h*(cat.sum_prices+Cost(cat.pairs.size())*popcount(g.bits));
        if(upper<saved(g.bits,groups,h))return {};
    }
    Tally tally;size_t inspected=0,limit=min(CAP,cat.pairs.size());
    for(size_t batch=16;inspected<limit;batch*=2){
        size_t stop=min(batch,limit);
        for(;inspected<stop;inspected++){
            auto &w=cat.pairs[inspected];tally.add(disagreement(w,q),w.price);
        }
        if(tally.proves(h,groups))return {true,inspected};
    }
    return {false,inspected};
}


bool audit(const Catalog& c,const vector<Q>& q,I n,Cost h,size_t used) {
    array<Cost,K> freq{},prices{};
    for(size_t i=0;i<used;i++){
        unsigned left=0,right=0;
        for(unsigned j=0;j<B;j++){
            left+=unsigned(accepts(c.pairs[i].l,q[j]))<<j;
            right+=unsigned(accepts(c.pairs[i].r,q[j]))<<j;
        }
        auto d=left^right;++freq[d];prices[d]+=c.pairs[i].price;
    }
    auto groups=group(q,n);
    for(unsigned keep=1;keep<K;keep++){
        Cost tree=0;
        for(unsigned d=1;d<K;d++)if(keep&d)tree+=prices[d]+freq[d]*popcount(keep&d);
        if(h*tree<saved(keep,groups,h))return false;
    }
    return true;
}
vector<U> load_rows(string prefix){
    ifstream f(prefix+".rows",ios::binary|ios::ate);auto len=f.tellg();

    const U max_rows=U(numeric_limits<int>::max())/2;
    if(len<=0||U(len)%sizeof(U)||U(len)/sizeof(U)>max_rows)throw runtime_error("Invalid row image");
    vector<U> rows(size_t(len)/sizeof(U));f.seekg(0);f.read(reinterpret_cast<char*>(rows.data()),len);
    if(!f)throw runtime_error("Short row file");return rows;
}
vector<Ans> direct(const vector<U>& rows,const vector<Q>& qs){
    vector<I> endpoints;
    for(auto s:qs[0].ranges){
        if(s.l>s.r||s.r>rows.size())throw runtime_error("Invalid row interval");
        endpoints.push_back(s.l);endpoints.push_back(s.r);
    }
    sort(endpoints.begin(),endpoints.end());
    endpoints.erase(unique(endpoints.begin(),endpoints.end()),endpoints.end());
    I cursor=0;Ans totals{};map<I,Ans> at;
    for(I stop:endpoints){
        for(;cursor<stop;cursor++)for(unsigned j=0;j<B;j++)totals[j]+=accepts(rows[cursor],qs[j]);
        at[stop]=totals;
    }
    vector<Ans> result;
    for(auto s:qs[0].ranges){
        Ans counts{};for(unsigned j=0;j<B;j++)counts[j]=at[s.r][j]-at[s.l][j];result.push_back(counts);
    }
    return result;
}
struct Cache {
    array<int,B> location; vector<Node> bits;
    Cache(Columns& cols,const vector<Q>& q,unsigned keep){
        location.fill(-1);map<pair<U,U>,int> ids;
        for(unsigned j=0;j<B;j++)if(!(keep&(1u<<j))){
            U fields=q[j].one|q[j].zero;
            if((q[j].one&q[j].zero)||!fields||has_single_bit(fields)){location[j]=-2;continue;}
            auto [it,fresh]=ids.emplace(make_pair(q[j].one,q[j].zero),int(bits.size()));
            if(fresh)bits.push_back(cols.cache(q[j]));location[j]=it->second;
        }
    }
    void counts(Ans& out,const Columns& cols,const vector<Q>& q,Range z) const {
        I counts[B];for(size_t k=0;k<bits.size();k++)counts[k]=bits[k].count(z);
        for(unsigned j=0;j<B;j++){
            int id=location[j]; if(id==-1)continue;if(id>=0){out[j]=counts[id];continue;}
            const Q& v=q[j];U mask=v.one|v.zero;
            if(v.one&v.zero)out[j]=0;else if(!mask)out[j]=z.r-z.l;
            else{int f=countr_zero(mask);I hit=cols.rankcol(f,z.r)-cols.rankcol(f,z.l);out[j]=v.one?hit:z.r-z.l-hit;}
        }
    }
};
void dataset(const string& prefix,ostream& out){
    vector<U> rows=load_rows(prefix);auto q=readq(prefix+".queries");
    if(q.empty()||q.size()%B)throw runtime_error("Invalid bundle count");
    Tree tree(rows); Columns cols(rows);
    auto begin=Clock::now();Catalog catalog(tree);auto catalog_ns=elapsed(begin);
    const string name=filesystem::path(prefix).filename().string();
    for(size_t i=0;i<q.size();i+=B){
        vector<Q> batch(q.begin()+i,q.begin()+i+B);
        auto &slices=batch[0].ranges;
        if(slices.empty()||slices.size()>4096)throw runtime_error("Horizon outside runner contract [1,4096]");
        for(auto& rule:batch)if(rule.ranges!=slices)throw runtime_error("Mismatched bundle intervals");
        const Cost h=Cost(slices.size());
        const auto truth=direct(rows,batch);
        auto inspected=decide(catalog,batch,tree.n,h);
        bool prefix_proof=audit(catalog,batch,tree.n,h,inspected.sampled);
        bool full_proof=audit(catalog,batch,tree.n,h,catalog.pairs.size());
        if(prefix_proof!=inspected.yes || (prefix_proof && !full_proof))throw logic_error("Witness audit mismatch");

        auto original=frontier(tree,batch,false);
        unsigned pk=partition(tree,original,batch,int(h),false);
        if(prefix_proof && pk!=0)throw logic_error("Contradiction with a feasible cheaper placement");
        constexpr const char* names[]={"cached_bitmaps","frontier_joint","portfolio","gated_portfolio"};
        for(int rep=0;rep<3;rep++)for(int t=0;t<4;t++){
            int m=(int(i/B)+rep+t)%4;
            Plan plan;unsigned keep=ALL;Decision d{};long long gate_ns=0;
            auto start=Clock::now();
            if(m==3){d=decide(catalog,batch,tree.n,h);gate_ns=elapsed(start);}
            if(m==0 || d.yes)keep=0;
            else{
                plan=frontier(tree,batch,false);
                if(m>=2){
                    keep=partition(tree,plan,batch,int(h),false);
                    for(auto& term:plan){term.plus&=keep;term.minus&=keep;}
                    plan.erase(remove_if(plan.begin(),plan.end(),[](auto e){return !(e.plus|e.minus);}),plan.end());
                }
            }
            Cache cache(cols,batch,keep);
            auto prep=elapsed(start);
            vector<Ans> ans(slices.size());
            start=Clock::now();
            for(size_t s=0;s<slices.size();s++){
                ans[s]=run(tree,plan,slices[s]);
                if(keep!=ALL)cache.counts(ans[s],cols,batch,slices[s]);
            }
            auto exec=elapsed(start);
            if(ans!=truth || (m==3 && (d.yes!=inspected.yes || d.sampled!=inspected.sampled)) ||
               (m>=2 && keep!=pk))throw logic_error("Oracle disagreement");
            U digest=0;
            for(auto a:ans)for(auto v:a)digest=digest*131+U(v);
            out<<name<<'\t'<<batch[0].id<<'\t'<<rep<<'\t'<<names[m]<<'\t'<<h<<'\t'<<keep<<'\t'
               <<inspected.yes<<'\t'<<full_proof<<'\t'<<catalog.pairs.size()<<'\t'<<inspected.sampled<<'\t'
               <<catalog.pairs.capacity()*sizeof(Witness)<<'\t'<<catalog_ns<<'\t'<<gate_ns<<'\t'
               <<prep<<'\t'<<exec<<'\t'<<digest<<'\n';
        }
    }
    out.flush();cout<<name<<": complete\n"<<flush;
}
}
int main(int argc,char** argv){
    try{
        if(argc<3)throw runtime_error("gate.exe output.tsv dataset_prefix [...]");
        ofstream out(argv[1]);if(!out)throw runtime_error("Cannot open output");
        out<<"dataset\tbundle\trep\tmethod\tslices\tkeep\tcertified\tfull_proof\tpairs\tinspected\tcatalog_bytes\tcatalog_ns\tgate_ns\tcompile_ns\texec_ns\tdigest\n";
        for(int k=2;k<argc;k++)gate::dataset(argv[k],out);
    }catch(const exception& e){cerr<<e.what()<<'\n';return 1;}
}
