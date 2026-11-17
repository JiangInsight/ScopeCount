
#define main bundles_entry
#include "bundles.cpp"
#undef main
#include <numeric>
#include <random>
using Freq=pair<U,I>;

int construct(Tree&tr,vector<Freq> v,int rule){
    int x=int(tr.t.size());tr.t.emplace_back();
    if(v.size()==1){tr.t[x].shape=tr.t[x].all=tr.t[x].any=v[0].first;return x;}
    array<U,64> ones{};U mass=0;
    for(auto [value,count]:v){
        U weight=rule==1?count:1;mass+=weight;
        for(;value;value&=value-1)ones[countr_zero(value)]+=weight;
    }
    int split=-1;U balance=0;for(int k=0;k<64;k++){
        U score=min(ones[k],mass-ones[k]);if(score>balance){balance=score;split=k;if(rule==2)break;}
    }
    if(split<0)throw logic_error("No split for distinct observations");
    vector<Freq> left,right;for(auto e:v)((e.first>>split&1)?right:left).push_back(e);
    int a=construct(tr,move(left),rule),b=construct(tr,move(right),rule);
    auto &nd=tr.t[x];nd.bit=split;nd.a=a;nd.b=b;nd.any=tr.t[a].any|tr.t[b].any;nd.all=tr.t[a].all&tr.t[b].all;
    return x;
}
void build(Tree&tr,const vector<U>&rows,int rule){
    tr.t.clear();tr.n=I(rows.size());unordered_map<U,I> freq;for(U x:rows)++freq[x];
    vector<Freq> values(freq.begin(),freq.end());sort(values.begin(),values.end());
    construct(tr,move(values),rule);
    for(I i=0;i<tr.n;i++){
        int x=0;while(tr.t[x].bit>=0){
            x=(rows[i]>>tr.t[x].bit&1)?tr.t[x].b:tr.t[x].a;tr.t[x].p.push_back(i);
        }
    }
    for(auto &v:tr.t)if(!v.p.empty()&&4ULL*v.p.size()>12ULL*((U(tr.n)+63)/64)+4){
        v.w.assign((U(tr.n)+63)/64,0);for(I i:v.p)v.w[i/64]|=U(1)<<(i%64);
        v.pref.resize(v.w.size()+1);
        for(size_t k=0;k<v.w.size();k++)v.pref[k+1]=v.pref[k]+popcount(v.w[k]);
        vector<I>().swap(v.p);
    }
}
long long physical(const Plan&p,const vector<pair<int,int>>&charge){
    long long cost=0;for(auto e:p)if(e.x)cost+=charge[e.x].first+charge[e.x].second*popcount(unsigned(e.plus|e.minus));return cost;
}
vector<Ans> oracle(const vector<U>&rows,const vector<Q>&q){
    const auto& r=q.front().ranges;vector<I> endpoints;
    for(auto z:r){if(z.l>z.r||z.r>rows.size())throw logic_error("Bad interval");endpoints.push_back(z.l);endpoints.push_back(z.r);}
    sort(endpoints.begin(),endpoints.end());endpoints.erase(unique(endpoints.begin(),endpoints.end()),endpoints.end());
    vector<Ans> result(r.size());
    for(int j=0;j<int(q.size());j++){
        vector<I> sums;I i=0,count=0;U mask=q[j].one|q[j].zero;
        for(I stop:endpoints){if(!(q[j].one&q[j].zero))for(;i<stop;i++)count+=((rows[i]&mask)==q[j].one);sums.push_back(count);}
        for(size_t k=0;k<r.size();k++)result[k][j]=sums[lower_bound(endpoints.begin(),endpoints.end(),r[k].r)-endpoints.begin()]
            -sums[lower_bound(endpoints.begin(),endpoints.end(),r[k].l)-endpoints.begin()];
    }return result;
}
vector<pair<int,int>> prices(const Tree&t){
    vector<pair<int,int>> ret;
    for(auto &v:t.t)ret.emplace_back(v.w.empty()?2+2*int(bit_width(v.p.size())):5,1);
    ret[0]={0,0};return ret;
}
void dataset(const string&pre,ostream&out){
    ifstream f(pre+".rows",ios::binary|ios::ate);auto bytes=f.tellg();
    if(bytes<=0||U(bytes)%8||U(bytes)/8>=UINT32_MAX)throw runtime_error("Bad rows");
    vector<U> rows(size_t(bytes)/8);f.seekg(0);f.read((char*)rows.data(),bytes);if(!f)throw runtime_error("Incomplete read");


    vector<U> placeholder{0};array<Tree,3> trees={Tree(placeholder),Tree(placeholder),Tree(placeholder)};
    array<long long,3> bt{};array<U,3> mem{};array<vector<pair<int,int>>,3> charge;
    for(int rule=0;rule<3;rule++){
        auto t0=Clock::now();build(trees[rule],rows,rule);bt[rule]=elapsed(t0);charge[rule]=prices(trees[rule]);
        mem[rule]=sizeof(Node)*trees[rule].t.capacity();
        for(auto &v:trees[rule].t)mem[rule]+=4*v.p.capacity()+4*v.pref.capacity()+8*v.w.capacity();
    }
    auto qs=readq(pre+".queries");if(qs.empty()||qs.size()%8)throw logic_error("Expected complete bundles");
    const array<string,3> name={"distinct","frequency","field"};string ds=pre.substr(pre.find_last_of("/\\")+1);mt19937 rand(8861);
    for(size_t i=0;i<qs.size();i+=8){
        vector<Q>q(qs.begin()+i,qs.begin()+i+8);for(auto &v:q)if(q[0].ranges!=v.ranges)throw logic_error("Different slice endpoints");
        auto truth=oracle(rows,q);U hash=0;for(auto a:truth)for(auto z:a)hash=hash*131+z;
        validatePrices(trees[0],8,1,1,&charge[0]);int verified=0;for(int b:{2,4}){
            vector<Q> sub(q.begin(),q.begin()+b);
            auto lab=leaflabels(trees[0],sub);
            auto exact=optimize(trees[0],lab,b,1,1,false,&charge[0]);auto quadratic=optimize(trees[0],lab,b,1,1,true,&charge[0]);
            if(physical(exact,charge[0])!=physical(quadratic,charge[0]))throw logic_error("Weighted oracle mismatch");
            for(auto& z:q[0].ranges)if(run(trees[0],exact,z)!=run(trees[0],quadratic,z))throw logic_error("Weighted backtrack mismatch");++verified;
        }
        for(int rep=0;rep<3;rep++){
            array<int,4> order={0,1,2,3};shuffle(order.begin(),order.end(),rand);
            for(int id:order){
                int rule=id%3;auto &t=trees[rule];auto start=Clock::now();Plan p;
                if(id<3)p=frontier(t,q,false);
                else{auto lab=leaflabels(t,q);p=solveValidatedPrices(t,lab,8,1,1,false,&charge[0]);}
                auto compilation=elapsed(start);vector<Ans> ans(q[0].ranges.size());start=Clock::now();
                for(size_t j=0;j<ans.size();j++)ans[j]=run(t,p,q[0].ranges[j]);
                auto eval=elapsed(start);if(ans!=truth)throw logic_error("Incorrect count "+ds);
                auto [r,u]=cost(p);
                out<<ds<<'\t'<<q.front().id<<'\t'<<name[rule]<<'\t'<<(id<3?"min_reads":"physical")<<'\t'<<rep<<'\t'<<r<<'\t'<<u<<'\t'
                   <<physical(p,charge[rule])<<'\t'<<compilation<<'\t'<<eval<<'\t'<<bt[rule]<<'\t'<<mem[rule]<<'\t'
                   <<t.t.size()<<'\t'<<ans.size()<<'\t'<<hash<<'\t'<<(id==3?verified:0)<<'\n';
            }
        }
    }out.flush();cout<<ds<<endl;
}
int main(int argc,char**argv){try{
    if(argc<3)throw runtime_error("topology.exe output.tsv prefixes...");
    ofstream out(argv[1]);if(!out)throw runtime_error("Could not create TSV");
    out<<"dataset\tbundle\ttree\tplanner\trep\tranks\tupdates\tphysical\tcompile_ns\texec_ns\tbuild_ns\tbytes\tnodes\tslices\tdigest\toracle_widths\n";
    for(int i=2;i<argc;i++)dataset(argv[i],out);return 0;
}catch(const exception&e){cerr<<e.what()<<'\n';return 1;}}
